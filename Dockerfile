FROM debian:bullseye

MAINTAINER romain.gehrig@gmail.com

RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends apt-utils \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
    && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip pdftk-java

RUN pip3 install --upgrade pip

RUN mkdir -p /opt/pdfcollate
WORKDIR /opt/pdfcollate
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY pdfcollate /opt/pdfcollate

RUN mkdir /files
RUN mkdir /output
VOLUME ["/files"]
VOLUME ["/output"]

WORKDIR /opt/pdfcollate

ENTRYPOINT ["/opt/entrypoint.sh"]

CMD ["python3", "event_watcher.py"]
