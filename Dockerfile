FROM python:3.4

ADD . /app/

WORKDIR /app

RUN pip install -U pip \
	&& pip install . \
	&& rm -rf ~/.cache

# Dashboard, monitoring and docs
EXPOSE 5555 20020 8000
