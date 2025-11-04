# BXF Schema Collection

## General

_This repository is *public*._

Please consult [CONTRIBUTING.md](./CONTRIBUTING.md), [CONFIDENTIALITY.md](./CONFIDENTIALITY.md), [LICENSE.md](./LICENSE.md) and
[PATENTS.md](./PATENTS.md) for important notices.

Your feedback is welcome at _link to GitHub issue tracker_ or at _TC chair email address_.

## Notice

The schema found here are made available to implementers of the BXF standard, under the controlling document SMPTE ST2021-4. A collection of schema is included for each version, identifiable by tags.

## Generated assets

This repository now includes derived artefacts that help document and explore the sample BXF traffic use cases:

* JSON Schema Draft 2020-12 conversions of the XML Schema definitions are published under [`schema-json/`](./schema-json). They can be regenerated locally with:

  ```bash
  python tools/xsd_to_jsonschema.py schema schema-json
  ```

* An AsyncAPI catalogue that groups the sample BXF messages by their `messageType` attribute is available at [`asyncapi/bxf-usecases.yaml`](./asyncapi/bxf-usecases.yaml). Rebuild it from the XML use cases with:

  ```bash
  python tools/build_asyncapi.py usecases schema-json asyncapi/bxf-usecases.yaml
  ```

* A lightweight documentation site that renders the AsyncAPI document is published in [`docs/`](./docs). Open [`docs/index.html`](./docs/index.html) in a browser to view a Swagger-like experience backed by the [`@asyncapi/web-component`](https://github.com/asyncapi/web-component).

