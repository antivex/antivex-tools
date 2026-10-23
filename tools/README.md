# How a tool is built

One folder per tool: `tools/<name>/` (lowercase, words separated by `_`).

Inside:

- `README.md`: the problem in one sentence, who it is for, how to run it (copy-paste commands),
  what it does NOT do, where the data goes.
- `<name>.py`: the tool. Python 3.10+ **standard library only** (no `pip install`), runs from the
  command line, `--help` explains every option, `--dry-run` when it writes to another service.
- `test_<name>.py`: tests with `unittest`, run offline (no network, no real accounts). Use small
  synthetic sample files in `tools/<name>/samples/`, never real personal data.

Run the tests of one tool:

```
python3 -m unittest discover -s tools/<name> -t tools/<name> -p "test_*.py"
```

Secrets (API keys) are read from command-line options or environment variables, never stored in
files and never printed.
