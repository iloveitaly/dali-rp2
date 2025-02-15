# Copyright 2022 eprbell
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

BIN := $(wildcard bin/*.py)
DALI_SRC := $(wildcard src/dali/*.py) $(wildcard src/dali/plugin/*.py) $(wildcard src/dali/plugin/input/*.py)
TEST_SRC := $(wildcard tests/*.py)
TESTS := $(wildcard tests/test_*.py)

PYTHONPATH := $(CURDIR)/src
VENV := .venv

DALI_MAKEFILE := 1

all: $(VENV)/bin/activate

$(VENV)/bin/activate: Makefile setup.py setup.cfg
	virtualenv -p python3 $(VENV)
	$(VENV)/bin/pip3 install -e ".[dev]"

run: $(VENV)/bin/activate
	rm -rf log/ output/

check: $(VENV)/bin/activate
	$(VENV)/bin/pytest --tb=native --verbose

static_analysis: $(VENV)/bin/activate
	MYPYPATH=$(PYTHONPATH):$(CURDIR)/src/stubs $(VENV)/bin/mypy src/ tests/
	$(VENV)/bin/pylint -r y src tests/*.py
	$(VENV)/bin/bandit -r src/

reformat: $(VENV)/bin/activate
	$(VENV)/bin/isort .
	$(VENV)/bin/black src/ tests/

archive: clean
	rm -f dali.zip || true
	zip -r dali.zip .

distribution: all
	$(VENV)/bin/pip3 install twine
	rm -rf build/ dist/
	$(VENV)/bin/python3 setup.py sdist bdist_wheel
	$(VENV)/bin/python3 -m twine check dist/*

upload_test_distribution: distribution
	$(VENV)/bin/pip3 install twine
	$(VENV)/bin/python3 -m twine upload --repository testpypi dist/*

upload_distribution: distribution
	$(VENV)/bin/pip3 install twine
	$(VENV)/bin/python3 -m twine upload dist/*

clean:
	rm -rf $(VENV) .dali_cache .mypy_cache/ .pytest_cache/ build dist/ log/ output/ src/*.egg-info/
	find . -type f -name '*.pyc' -delete

.PHONY: all archive check clean lint reformat run securitycheck typecheck
