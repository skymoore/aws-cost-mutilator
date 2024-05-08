default: build

lock:
	poetry lock

.PHONY: clean
clean:
	rm -rf dist

.PHONY: patch
patch:
	poetry version patch

.PHONY: minor
minor:
	poetry version minor

.PHONY: major
major:
	poetry version major

build: clean
	poetry build
