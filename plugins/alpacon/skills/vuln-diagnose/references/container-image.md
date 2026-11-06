# Container images

From the host, the check can read which image a container runs, not what is inside it. A library inside the image (a Python package in a Langflow container, for instance) is `unknown` from the host; say which container and image, so a person can check the image itself. Do not `docker exec` into a container from this skill: it runs a process inside the workload, which is more than a read.

```sh
docker ps --format 'container={{.Names}} image={{.Image}}' 2>&1 || podman ps --format 'container={{.Names}} image={{.Image}}' 2>&1
```

- The image tag carries a version, and the image is the vulnerable software: compare the tag with the fixed version.
- The tag is `latest`, a branch name, or a digest only: `unknown`. A digest says which build runs but not which version it is, unless the vendor publishes digests per version.
- Reading the Docker socket needs root or membership of the `docker` group, which amounts to root. If the command fails with a permission error, the row is `unknown`; do not add `sudo` to get past it without the person deciding the session should carry it.
- Kubernetes workloads are out of reach from a node's shell; report them as `unknown`.

Upgrading a container means pulling a new image and redeploying, which `vuln-remediate` reports for a person and does not do.
