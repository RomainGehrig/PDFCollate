#!/usr/bin/env python3
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Optional

import pyinotify
from dateutil import parser
from pydantic import BaseModel
from PyPDF4 import PdfFileReader, PdfFileWriter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


def parse_timedelta(d: str) -> timedelta:
    # Datetime parsed is relative to today 00:00, so we need to subtract this time
    parsed = parser.parse(d)
    now = datetime.now()
    today = datetime(year=now.year, month=now.month, day=now.day)
    return parsed - today


SOURCE_DIRECTORY = os.getenv("SOURCE_DIRECTORY", "/files")
DESTINATION_DIRECTORY = os.getenv("DESTINATION_DIRECTORY", "/output")
COLLATE_TIMEOUT = parse_timedelta(os.getenv("COLLATE_TIMEOUT", "10m"))
OUTPUT_NAME_SUFFIX = os.getenv("OUTPUT_NAME_SUFFIX", "-collated")
DELETE_OLD_FILES = os.getenv("DELETE_OLD_FILES", "true").lower() in ["true", 1]
mask = pyinotify.IN_CREATE | pyinotify.IN_CLOSE_WRITE


# Goal: if two pdf files that can be merged together are created within a certain time from one another,
# then collate them and move the resulting file in the output directory

# Timeout starts when the last file is close and finish when the new file is created

# Compatible PDFs: Same number of pages

# Process:
# 1) When a file is created, see if it is a PDF: if no then forget about it, if yes continue
#    - If no PDF file was created within the last COLLATE_TIMEOUT, then this new file will be the "First"
#    - If a "First" PDF file was created but COLLATE_TIMEOUT passed, then issue a warning that "First" timeout and this file will be "First"
#    - Else if a new PDF was created within the last COLLATE_TIMEOUT, then this file will be the "Second"
# 2) When file is close write (finished writing to by the process), then a check is done:
#    - If the file was "First", then go to 1) and wait for new file
#    - If the file was "Second", and PDFs "First" and "Second" are compatible, then go to to 3)
#    - If the file was "Second" but the PDFs aren't compatible, then print warning that First is orphaned and set First=Second, then go to 1) and wait
# 3) Merge PDFs "First" and "Second" with pdftk command: `pdftk A=first.pdf B=second.pdf shuffle A Bend-1 output collated.pdf`
# 4) If successful, remove the two old files from the directory and from the watching process (First=None, Second=None)


class PDF(BaseModel):
    path: Path
    created: datetime
    ended: Optional[datetime]


class State(Enum):
    WAITING_FOR_FIRST = "WAITING_FOR_FIRST"
    RECEIVING_FIRST = "RECEIVING_FIRST"
    WAITING_FOR_SECOND = "WAITING_FOR_SECOND"
    RECEIVING_SECOND = "RECEIVING_SECOND"
    PROCESSING = "PROCESSING"


def pdfs_are_compatible(first, second):
    try:

        def get_page_number(pdf_path):
            with open(pdf_path, "rb") as f:
                return PdfFileReader(f).getNumPages()

        return get_page_number(first) == get_page_number(second)
    except:
        return False


def merge_pdfs(first_path, second_path, destination):
    with open(first_path, "rb") as f1:
        with open(second_path, "rb") as f2:
            first = PdfFileReader(f1)
            second = PdfFileReader(f2)

            output_pdf = PdfFileWriter()

            # first is normal, second has pages in reverse order
            pages = zip(range(first.getNumPages()), range(second.getNumPages() - 1, 0 - 1, -1))
            for p1, p2 in pages:
                output_pdf.addPage(first.getPage(p1))
                output_pdf.addPage(second.getPage(p2))

            with open(destination, "wb") as f:
                output_pdf.write(f)
            input_stats = os.stat(first_path)
            os.chown(destination, input_stats.st_uid, input_stats.st_gid)
            os.chmod(destination, input_stats.st_mode)

            return


def only_pdfs(f):
    @wraps(f)
    def fun(self, event, *args, **kwargs):
        if not event.pathname.endswith(".pdf"):
            logger.info(f"Skipping file {event.pathname} because it is not a PDF")
            return
        return f(self, event, *args, **kwargs)

    return fun


class PDFCollateWatch(pyinotify.ProcessEvent):
    def __init__(self, timeout, output_dir, name_suffix, delete_old_files, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.first: PDF = None
        self.second: PDF = None
        self._state = State.WAITING_FOR_FIRST
        self.timeout = timeout
        self.output_dir = output_dir
        self.delete_old_files = delete_old_files
        self.name_suffix = name_suffix or ""

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        if new_state != self._state:
            logger.debug(f"Changed state from {self._state} to {new_state}")
        self._state = new_state

    def reset_state(self):
        logger.error(f"Resetting state from {self.state}: first was {self.first}, second was {self.second}")
        self.first: PDF = None
        self.second: PDF = None
        self.state = State.WAITING_FOR_FIRST

    @only_pdfs
    def process_IN_CREATE(self, event):
        now = datetime.now()
        pdf = PDF(path=Path(event.pathname), created=now, ended=None)
        logger.info(f"Event CREATE for {event.pathname}")

        while self.state in [State.PROCESSING, State.RECEIVING_FIRST, State.RECEIVING_SECOND]:
            logger.warning(f"State is busy ({self.state}), waiting 2 sec to process {pdf.path}")
            time.sleep(2)

        if self.state == State.WAITING_FOR_FIRST:
            self.state = State.RECEIVING_FIRST
            self.first = pdf
            return

        if self.state == State.WAITING_FOR_SECOND:
            # Case where we waited for too long after first was created:
            if now - self.first.ended > self.timeout:
                logger.warning(
                    f"Collate timeout: {self.first.path} was discarded from first position and {pdf.path} took its place."
                )
                self.state = State.WAITING_FOR_SECOND
                self.first = pdf
                return

            # Else
            self.state = State.RECEIVING_SECOND
            self.second = pdf

    @only_pdfs
    def process_IN_CLOSE_WRITE(self, event):
        # Filter out files that are not being received
        current_files = [
            self.first.path.as_posix() if self.first is not None else None,
            self.second.path.as_posix() if self.second is not None else None,
        ]
        if event.pathname not in current_files:
            logger.warning(f"Skipping close write event for {event.pathname} as it is not in {current_files}")
            return

        # Illegal state sanity check
        if self.state in [State.PROCESSING, State.WAITING_FOR_FIRST, State.WAITING_FOR_SECOND]:
            logger.error(f"Reached an illegal state ! A file was closed (write) while state was {self.state}.")
            self.reset_state()
            return

        now = datetime.now()
        if self.state == State.RECEIVING_FIRST:
            self.first.ended = now
            self.state = State.WAITING_FOR_SECOND
            logger.info(f"Write close for {self.first.path}")
            return

        if self.state == State.RECEIVING_SECOND:
            self.second.ended = now
            if not pdfs_are_compatible(self.first.path, self.second.path):
                logger.warning(
                    f"PDFs are not compatible: {self.first.path} & {self.second.path}, removing {self.first.path}"
                )
                self.first, self.second = self.second, None
                self.state = State.WAITING_FOR_SECOND
                return

            name, ext = os.path.splitext(self.first.path.name)
            destination_name = name + self.name_suffix + ext
            destination = Path(self.output_dir, destination_name)

            merge_successful = False
            try:
                logger.info(f"Starting processing of {self.first.path} and {self.second.path}")
                self.state = State.PROCESSING

                merge_pdfs(self.first.path, self.second.path, destination=destination)
                merge_successful = True
            except:
                logger.exception(f"Error while processing {self.first.path} and {self.second.path}")
            finally:
                logger.info(f"End of processing for {self.first.path} and {self.second.path} -> {destination}")
                if self.delete_old_files and merge_successful:
                    self.first.path.unlink()
                    self.second.path.unlink()
                self.first = None
                self.second = None
                self.state = State.WAITING_FOR_FIRST


print(f"PDFCollate watching for files in {SOURCE_DIRECTORY}, output to {DESTINATION_DIRECTORY}")
wm = pyinotify.WatchManager()
handler = PDFCollateWatch(COLLATE_TIMEOUT, DESTINATION_DIRECTORY, OUTPUT_NAME_SUFFIX, DELETE_OLD_FILES)
notifier = pyinotify.Notifier(wm, handler)
wdd = wm.add_watch(SOURCE_DIRECTORY, mask, rec=True)

notifier.loop()
