#!/bin/zsh
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print 'Set up Python first; see README.md.'
  exit 1
fi
exec .venv/bin/python app.py
