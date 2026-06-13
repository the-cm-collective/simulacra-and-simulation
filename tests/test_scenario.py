from __future__ import annotations

from pathlib import Path

from simulacra.scenario import load_scenario


def test_default_scenario_points_at_padawan_sibling(tmp_path: Path) -> None:
    scenario = load_scenario(tmp_path)

    assert scenario.name == "padawan-peer"
    assert scenario.target_label == "Padawan"
    assert scenario.target_root == tmp_path.parent / "padawan"
    assert scenario.k1s_root == tmp_path.parent / "k1s"
    assert scenario.workerbee_root == tmp_path.parent / "k1s-workerbee"
    assert scenario.k1s_ingress["probe_body_contains"] == "Padawan"


def test_scenario_yaml_and_overrides_replace_target_repo(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenarios"
    scenario_dir.mkdir()
    scenario_file = scenario_dir / "custom.yaml"
    scenario_file.write_text(
        """
name: custom-feature
target:
  label: CustomApp
  repo_root: ../custom-app
  feature_prompt: Add custom feature.
k1s_ingress:
  namespace: custom-ns
  probe_body_contains: Custom Ready
workerbee_stage:
  manifest: manifests/custom.k1s.yaml
  env_updates:
    CUSTOM_HOST: "{app_host}"
""".lstrip(),
        encoding="utf-8",
    )

    scenario = load_scenario(
        tmp_path,
        scenario_file,
        overrides=["target.label=OverriddenApp", "k1s_ingress.probe_body_contains=Ready"],
    )

    assert scenario.name == "custom-feature"
    assert scenario.target_label == "OverriddenApp"
    assert scenario.target_root == tmp_path / "custom-app"
    assert scenario.feature_prompt == "Add custom feature."
    assert scenario.k1s_ingress["namespace"] == "custom-ns"
    assert scenario.k1s_ingress["probe_body_contains"] == "Ready"
    assert scenario.workerbee_stage["manifest"] == "manifests/custom.k1s.yaml"
    assert scenario.workerbee_stage["env_updates"]["CUSTOM_HOST"] == "{app_host}"
