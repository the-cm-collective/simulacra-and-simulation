from __future__ import annotations

from pathlib import Path

import yaml

from simulacra.workerbee_stage import patch_padawan_stage, patch_stage


def test_patch_padawan_stage_updates_ingress_and_turn_host(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "stage" / "manifests"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "padawan.k1s.yaml"
    manifest_path.write_text(
        """
apiVersion: ae.dev/v1alpha1
kind: Deployment
metadata:
  name: padawan
spec:
  env:
    - name: PADAWAN_TURN_HOST
      value: old.example.test
    - name: PADAWAN_PORT
      value: "8787"
  ingress:
    host: old.example.test
    path: /
    tls: true
""".lstrip(),
        encoding="utf-8",
    )

    result = patch_padawan_stage(tmp_path / "stage", project="simcal2")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    env = {item["name"]: item["value"] for item in manifest["spec"]["env"]}

    assert result["app_host"] == "app.simcal2.workerbee.localhost"
    assert manifest["spec"]["ingress"]["host"] == "app.simcal2.workerbee.localhost"
    assert env["PADAWAN_TURN_HOST"] == "app.simcal2.workerbee.localhost"


def test_patch_stage_uses_custom_manifest_and_env_templates(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "stage" / "manifests"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "custom.k1s.yaml"
    manifest_path.write_text(
        """
apiVersion: ae.dev/v1alpha1
kind: Deployment
metadata:
  name: custom
spec:
  env:
    - name: CUSTOM_HOST
      value: old.example.test
  ingress:
    host: old.example.test
""".lstrip(),
        encoding="utf-8",
    )

    result = patch_stage(
        tmp_path / "stage",
        project="custom-proj",
        stage_config={
            "manifest": "manifests/custom.k1s.yaml",
            "domain": "workerbee.test",
            "app_host_template": "{project}.{domain}",
            "ingress_host_path": "spec.ingress.host",
            "env_updates": {
                "CUSTOM_HOST": "https://{app_host}",
                "CUSTOM_PROJECT": "{project}",
            },
        },
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    env = {item["name"]: item["value"] for item in manifest["spec"]["env"]}

    assert result["app_host"] == "custom-proj.workerbee.test"
    assert manifest["spec"]["ingress"]["host"] == "custom-proj.workerbee.test"
    assert env["CUSTOM_HOST"] == "https://custom-proj.workerbee.test"
    assert env["CUSTOM_PROJECT"] == "custom-proj"
