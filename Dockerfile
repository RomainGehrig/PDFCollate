FROM alpine:3.8

MAINTAINER romain.gehrig@gmail.com

# INSTALL pdftk
RUN apk update && apk upgrade \
	&& apk add pdftk \
	&& apk add python3 \
    && apk add py3-pip

COPY . /opt/
WORKDIR /opt/
RUN pip3 install --upgrade pip
RUN pip3 install -r requirements.txt

RUN mkdir /files
RUN mkdir /output
VOLUME ["/files"]
VOLUME ["/output"]

WORKDIR /opt/pdfcollate

ENTRYPOINT ["/opt/entrypoint.sh"]
