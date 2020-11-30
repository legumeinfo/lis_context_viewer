# Protocol Buffers

GCV uses [gRPC](https://grpc.io/) for service-service and client-service communication.
This directory contains the [Protocol Buffers](https://developers.google.com/protocol-buffers) (protobufs) that define the API.
Using the [`protoc`](https://grpc.io/docs/protoc-installation/) compiler, code for interacting with protobufs and the gRPC services they define can be generated for a variety of programming languages.

The following are examples of how to use `protoc` to generate code from the protobufs for use within the GCV codebase.

### Python

    $ cd proto/
    proto/ $ mkdir python
    proto/ $ virtualenv venv
    proto/ $ . ./venv/bin/active
    proto/ (venv) $ pip install grpcio-tools
    proto/ (venv) $ python -m grpc_tools.protoc -I./ \
                    --python_out=./python \
                    --grpc_python_out=./python \
                    ./structures/*.proto ./services/*.proto --experimental_allow_proto3_optional

### TypeScript

Currently, gRPC requests cannot be sent natively from web browsers due to a lack of support for HTTP/2.
So, for the time being, web browsers must use the [gRPC Web protocol](https://grpc.io/blog/state-of-grpc-web/), which specifies how to send gRPC requests over HTTP/1.1 and use a proxy as a mediary that translates requests/responses between gRPC native services and web browsers.

To begin, install `protoc`.
Since GCV uses [Proto3](https://developers.google.com/protocol-buffers/docs/proto3) with [optional fields](https://github.com/protocolbuffers/protobuf/blob/v3.12.0/docs/field_presence.md), the version of `protoc` installed must be `1.13.0` or later.
Additionally, the [`grpc-web` plugin](https://github.com/grpc/grpc-web) must be installed.
Again, since GCV uses Proto3 with optional fields, version `1.2.1` or later of the plungin is required.

Once `protoc` and the `grpc-web` plugin are installed, JavaScript files with TypeScript bindings can be generated as follows:

    $ cd proto/
    proto/ $ mkdir typescript
    protoc $ protoc -I=./ \
             --js_out=import_style=commonjs,binary:./typescript \
             --grpc-web_out=import_style=typescript,mode=grpcwebtext:./typescript \
             ./structures/*.proto ./services/*.proto --experimental_allow_proto3_optional
