#!/usr/bin/env bash
# Runs the 4 C90 mappings in order. PYTHON overrides the interpreter.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
py="${PYTHON:-$here/../../../.venv/Scripts/python}"
for m in stg_sensitivity dw_sensitivity_usd calc_sbm_charge rpt_c90_facts; do
    "$py" "$here/pmrun.py" "$here/m_C90_$m.xml"
done
