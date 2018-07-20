FROM alpine:latest

LABEL maintainer Mikael Ganehag Brorsson <mikael.brorsson@gmail.com>

ENV HOME /home/docker/code/app

COPY requirements.txt /tmp/
COPY src/form.py src/main.py src/models.py application.py /home/docker/code/app/src/
COPY static /home/docker/code/app/static
COPY templates /home/docker/code/app/templates
COPY translations /home/docker/code/app/translations
COPY run.sh /home/docker/code/app/src/

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
    libmemcached-dev \
    postgresql-dev && \
  ln -sf /usr/include/locale.h /usr/include/xlocale.h && \
  \
  echo "====> pip install requirements.txt..." && \
  pip3 install -r /tmp/requirements.txt && \
  rm /tmp/requirements.txt && \
  \
  ln -sf /etc/pnyx/config.yaml /home/docker/code/app/src/config.cfg && \
  ln -sf /etc/pnyx/config.yaml /home/docker/code/app/src/config.yaml && \
  ln -sf /etc/pnyx/config.yaml /home/docker/code/app/src/server.cfg && \
  \
  echo "====> clean up..." && \
  apk del build-dependencies


ENTRYPOINT ["/sbin/tini", "--"]

WORKDIR /home/docker/code/app/src

EXPOSE 80

CMD ["./run.sh"]
