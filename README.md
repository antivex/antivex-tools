# antivex tools

Small, free, open-source tools that fix everyday annoyances: moving your own data out of an app that
shuts down or starts charging, connecting two services that don't talk to each other, removing a
repetitive chore.

No accounts, no ads, no tracking. Each tool runs on your computer and only talks to the services you
point it at.

## Tools

Each tool lives in its own folder under [`tools/`](tools/) with a README that explains what it does,
how to run it and its limits.

- [`withings_to_intervals`](tools/withings_to_intervals/): send your Withings weight, body fat and
  blood pressure export to intervals.icu (or a clean CSV) without Withings+.

## How to run a tool

You only need Python 3.10 or newer. No packages to install:

```
python3 tools/<tool>/<tool>.py --help
```

## Support

The tools are free. If one saved you time, you can buy me a coffee: https://ko-fi.com/antivex

Bug or idea? Open an issue.
