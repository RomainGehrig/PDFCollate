# What's that

When you want to scan documents on both sides but your automatic document feeder (ADF) only scan one side, then this project may help you.

If you just want to merge two PDFs in the correct order once and have pdftk installed on your machine, the command is `pdftk A=first.pdf B=second.pdf shuffle A Bend-1 output collated.pdf` (adapt names to your situation). This project does it automagically for you.


# How does it work

Watch PDFs files created in `SOURCE_DIRECTORY`. The first one will be used as is. The second one will be used with its page in reverse order (because we flip the document and start scanning from the end). The resulting PDF file will be created in `DESTINATION_DIRECTORY`.

How common problems are solved:

-   **Merging a new PDF with an old one:** There is a timeout `COLLATE_TIMEOUT` that runs from the moment the first PDF is done writing (event `IN_CLOSE_WRITE`). If a new PDF is created (event `IN_CREATE`) before the timeout ends, then this new PDF is understood to be the second one. Otherwise (timeout passed), the new PDF becomes the first one and the previous one is evicted with a timeout warning.
-   **Merging incompatible PDFs:** The number of pages should be equal for PDFs to be merged. If it's not the case, the second PDF replaces the first with a warning.

Limitations:

-   Depends on inotify, so it can be used only on Linux (Docker can solve that).
-   Cannot distinguish between PDFs coming from your scanner and those created differently (eg. copied or temporary file). Set `SOURCE_DIRECTORY` to a directory where your scanner is the only one to write to, with no subdirectory. Also, don't set `DESTINATION_DIRECTORY` to the same directory.


# Installation and configuration

The Docker image is available as [`cranium/pdfcollate`](https://hub.docker.com/r/cranium/pdfcollate).

Also available is a Python package you can download with `pip install pdfcollate`.

My usage of the project:

-   I have a NAS with two SAMBA directories: one for single-sided scans (`/Scans`), and the other for two-sided scans (`/DuplexScans`).
-   My NAS docker-compose uses the project's Dockerfile and sets two volumes `/DuplexScans:/files` and `/Scans:/output`.
-   My scanner has the two SAMBA directories as possible scan destinations. When I want to scan both sides: I put the document in the ADF, select scan to duplex directory (this scans one side), then retrieve the document from the tray, put it *on its flip side*, and select scan to duplex directory again. Once the scan is done, PDFCollate finds both documents and creates the collated document in the destination directory.


## Environment variables used by the Python script:

-   **`SOURCE_DIRECTORY`:** Directory watched for new PDF files
-   **`DESTINATION_DIRECTORY`:** Where the collated PDF will be created
-   **`COLLATE_TIMEOUT`:** How much time before we consider two PDFs to be unrelated.
-   **`OUTPUT_NAME_SUFFIX`:** Added to the output PDF name between the document name and `.pdf`


# Why

*Necessity is the mother of innovation.* And I needed to scan both sides without too much hassle.


# TODOs (don't hesitate to make a PR!)

-   **Upgrade alpine:** Stuck at alpine:3.8 because it has the pdftk binary.
-   **Document utilisation:** Can be used as pure Python, as a Docker image, or in a docker-compose file
-   **Add CLI arguments for configuration:** For improved flexibility
-   **Add tests:** Making sure we do the right thing in every case.
-   **Remove old files:** Once the merge is successful, we can remove the two old PDFs.

# Done
-   **Make it a Python package:** Would enable one-off use. Eg: `python3 -m pdfcollate`
-   **Publish image to Docker registry:** Easier installation and docker-compose integration~~
-   **Improve file permissions:** We should copy the input file permissions to the output files.

