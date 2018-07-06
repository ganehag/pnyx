FROM alpine:latest

LABEL maintainer Mikael Ganehag Brorsson <mikael.brorsson@gmail.com>

ENV HOME /home/docker/code/app

COPY requirements.txt /tmp/
COPY form.py main.py models.py /home/docker/code/app/
COPY static /home/docker/code/app/static
COPY templates /home/docker/code/app/templates
COPY run.sh /home/docker/code/app/

RUN apk add --update --no-cache ca-certificates tini

RUN apk add --no-cache --update python3 libpq libxslt xmlsec && \
    python3 -m ensurepip && \
    rm -r /usr/lib/python*/ensurepip && \
    pip3 install --no-cache-dir --upgrade pip setuptools && \
    \
    apk add --no-cache --virtual=build-dependencies \
    build-base \
    git \
    python3-dev \
    libxslt-dev \
    xmlsec-dev \
    postgresql-dev && \
  ln -sf /usr/include/locale.h /usr/include/xlocale.h && \
  \
  echo "====> pip install requirements.txt..." && \
  pip3 install -r /tmp/requirements.txt && \
  rm /tmp/requirements.txt && \
  \
  mkdir -p /home/docker/code/app/saml && \
  ln -sf /etc/wmbusgw/config.cfg /home/docker/code/app/config.cfg && \
  ln -sf /etc/wmbusgw/config.yaml /home/docker/code/app/config.yaml && \
  ln -sf /etc/wmbusgw/config.yaml /home/docker/code/app/server.cfg && \
  ln -sf /etc/wmbusgw/settings.json /home/docker/code/app/saml/settings.json && \
  ln -sf /etc/wmbusgw/advanced_settings.json /home/docker/code/app/saml/advanced_settings.json && \
  \
  echo "====> clean up..." && \
  apk del build-dependencies


ENTRYPOINT ["/sbin/tini", "--"]

WORKDIR /home/docker/code/app

EXPOSE 80

CMD ["./run.sh"]
