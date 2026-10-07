# Investment Instruction API

This repository contains the OpenAPI contract and Persian investment journey;
there is no service implementation here.

- [openapi.yaml](openapi.yaml): normative wire contract, version 2.0.0.
- [investment-journey.md](investment-journey.md): financial posting and independent daily market execution.
- [contract-review.md](contract-review.md): findings, compatibility impact and implementation considerations.

## Validate

Use Python 3.10+ in a virtual environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The checks validate the OpenAPI structure, every embedded request/response
example, financial arithmetic in examples, and important wire-schema boundaries.
They do not test a backend. Batch aggregation, control-total comparisons,
authorization, atomic ledger posting and per-account concurrency are documented
business rules which require integration tests in the implementing service.

## Compatibility

Version 2.0.0 removes PARTIALLY_COMPLETED from individual instructions, makes
instruction amounts non-null, requires amount in instruction details, permits
signed cash/net value, defines batch identity and aggregation, and permits null
instructionId only in rejected submission results. Regenerate clients and review
existing consumers before adopting this contract.
