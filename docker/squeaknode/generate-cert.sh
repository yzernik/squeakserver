#!/bin/bash

set -e
set -x

# Create Root signing Key
openssl genrsa -out ca.key 4096

# Generate self-signed Root certificate
openssl req -new -x509 -key ca.key -sha256 -subj "/C=US/ST=NJ/O=CA, Inc." -days 365 -out ca.cert

# Create a Key certificate for the Server
openssl genrsa -out service.key 4096

# Create a signing CSR
openssl req -new -key service.key -out service.csr -config certificate.conf

# Generate a certificate for the Server
openssl x509 -req -in service.csr -CA ca.cert -CAkey ca.key -CAcreateserial -out service.pem -days 365 -sha256 -extfile certificate.conf -extensions req_ext

# Verify
openssl x509 -in service.pem -text -noout
