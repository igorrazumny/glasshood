# Backend activation is explicit; these targets never run on commit or merge.
.PHONY: image deploy-image upload-landscape deploy-controller wake-scale
REVISION ?= HEAD

image:
	@test -n "$(IMAGE)" || { echo 'Set IMAGE to the versioned image name'; exit 1; }
	@set -eu; context=$$(mktemp -d); trap 'rm -rf "$$context"' EXIT; \
	git archive "$(REVISION)" > "$$context/source.tar"; \
	tar -xf "$$context/source.tar" -C "$$context"; rm "$$context/source.tar"; \
	docker buildx build --platform linux/amd64 -t "$(IMAGE)" --push "$$context"

deploy-image:
	@test -n "$(IMAGE)" || { echo 'Set IMAGE to the reviewed image name'; exit 1; }
	bash controller/deploy/cutover.sh prepare "$(IMAGE)"

upload-landscape:
	@test -f "$(LANDSCAPE)" && test -n "$(STORAGE_ACCOUNT)" && test -n "$(SHARE)" && test -n "$(REMOTE_PATH)" || \
	{ echo 'Set LANDSCAPE, STORAGE_ACCOUNT, SHARE and REMOTE_PATH'; exit 1; }
	az storage file upload --account-name "$(STORAGE_ACCOUNT)" --share-name "$(SHARE)" \
		--source "$(LANDSCAPE)" --path "$(REMOTE_PATH)" --auth-mode login --enable-file-backup-request-intent --output none

# REQ-GHA-018: publish the wake controller's reviewed code (function_app.py, host.json, requirements.txt, wake/)
deploy-controller:
	@set -eu; zipfile=$$(mktemp -t controller).zip; \
	git archive --format=zip -o "$$zipfile" "$(REVISION):controller" function_app.py host.json requirements.txt wake; \
	az functionapp deployment source config-zip -g rg-glasshood-azure -n func-glasshood-wake \
		--src "$$zipfile" --build-remote true -o none </dev/null

# REQ-GHA-018 third amendment: the app's wake check interval and cooldown
wake-scale:
	bash controller/deploy/cutover.sh scale
