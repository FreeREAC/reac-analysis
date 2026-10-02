# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>

test:
	python3 test_reac_tools.py
	python3 test_reac_repacer.py
	python3 -m unittest discover -s tools -p 'test_*.py'
.PHONY: test
