FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
	python3-pip \
	python3-psycopg2 \
	git

WORKDIR /

COPY requirements.txt /

RUN pip3 install --upgrade pip && \
	pip3 install -r requirements.txt

WORKDIR /app

# Copy the source code.
COPY . ./

RUN python3 setup.py install

EXPOSE 8774
EXPOSE 8994
EXPOSE 18774
EXPOSE 18994
# Web server
EXPOSE 12994

# Copy the entrypoint script.
COPY "docker/squeaknode/start-squeaknode.sh" .
RUN chmod +x start-squeaknode.sh

COPY "docker/squeaknode/generate-cert.sh" certs/
COPY "docker/squeaknode/certificate.conf" certs/
RUN chmod +x certs/generate-cert.sh

RUN cd certs && \
	./generate-cert.sh

RUN cd certs && \
	ls -l
