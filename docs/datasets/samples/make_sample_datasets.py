"""生成几个示例数据集（ZIP 包），用来试「上传数据 → 用它跑仿真」。

包内三个文件，与导入校验要求一致：

    manifest.json      元数据（schema_version / coordinate_frame / units / time_convention）
    truth.csv          必填。列：time_step,target_id,x,y
    observations.csv   必填（本版本仅用于通过导入校验；仿真只用 truth.csv）

关于 truth.csv 的两点：

* **只要 time_step,target_id,x,y 四列**，列顺序不限（按列名查）。多出来的列会被忽略，
  包括 velocity_x/velocity_y —— 速度不是读进来的，而是由相邻两步的位置差分重建，
  并按配置里的 time_stepSeconds 缩放。所以换个步长重跑同一个数据集，速度依然正确。
* `步数 = 最大 time_step + 1`。

用法：python make_sample_datasets.py [输出目录]
"""
from __future__ import annotations

import io
import json
import math
import random
import sys
import zipfile
from pathlib import Path

MANIFEST = {
    "schema_version": "1.0",
    "coordinate_frame": "ENU",
    "units": "meters",
    "time_convention": "seconds",
    "description": "FusionPilot sample dataset",
}


def build_zip(targets: list[dict], steps: int) -> bytes:
    """targets: [{id, x0, y0, vx, vy}]；steps 为总步数（含 step 0）。"""
    truth = ["time_step,target_id,x,y"]
    observations = ["time_step,sensor_id,source_type,x,y"]
    for step in range(steps):
        for target in targets:
            x = target["x0"] + target["vx"] * step
            y = target["y0"] + target["vy"] * step
            truth.append(f"{step},{target['id']},{x:.6f},{y:.6f}")
            observations.append(f"{step},RADAR-{target['id']:02d},RADAR,{x:.6f},{y:.6f}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(MANIFEST, ensure_ascii=False, indent=2))
        archive.writestr("truth.csv", "\n".join(truth) + "\n")
        archive.writestr("observations.csv", "\n".join(observations) + "\n")
    return buffer.getvalue()


def random_targets(count: int, seed: int, width: float, height: float,
                   speed_range=(2.0, 6.0)) -> list[dict]:
    """每个目标独立抽起点、航向、速度 —— 排布随机，但各自匀速直线。

    匀速是刻意的：融合策略假定匀速，真值若机动，误差里就混进了「模型失配」，
    那时看到的偏差不能算到滤波器头上。
    """
    rng = random.Random(seed)
    targets = []
    for target_id in range(1, count + 1):
        heading = rng.uniform(0, 2 * math.pi)
        speed = rng.uniform(*speed_range)
        targets.append({
            "id": target_id,
            "x0": rng.uniform(0.1 * width, 0.9 * width),
            "y0": rng.uniform(0.1 * height, 0.9 * height),
            "vx": speed * math.cos(heading),
            "vy": speed * math.sin(heading),
        })
    return targets


def crossing_targets(seed: int = 21) -> list[dict]:
    """四个目标分别从四角出发、大致奔向中心，会在场景中部交叉。

    交叉点最考验多目标跟踪：目标彼此靠近时，观测和航迹的对应关系最容易出错。
    """
    rng = random.Random(seed)
    corners = [(200.0, 200.0), (1800.0, 200.0), (180.0, 1060.0), (1820.0, 1040.0)]
    targets = []
    for index, (x0, y0) in enumerate(corners):
        # 朝 (1000, 620) 附近，加一点角度抖动，避免四条轨迹交于同一个点
        tx = 1000.0 + rng.uniform(-90, 90)
        ty = 620.0 + rng.uniform(-70, 70)
        dx, dy = tx - x0, ty - y0
        distance = math.hypot(dx, dy)
        speed = rng.uniform(2.5, 4.5)
        targets.append({
            "id": index + 1,
            "x0": x0,
            "y0": y0,
            "vx": speed * dx / distance,
            "vy": speed * dy / distance,
        })
    return targets


SAMPLES = [
    ("sample-random-3-targets.zip", lambda: random_targets(3, seed=7, width=2000, height=1200), 121),
    ("sample-random-8-targets.zip", lambda: random_targets(8, seed=11, width=2400, height=1400), 301),
    ("sample-crossing-4-targets.zip", crossing_targets, 201),
]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, factory, steps in SAMPLES:
        targets = factory()
        payload = build_zip(targets, steps)
        path = out_dir / name
        path.write_bytes(payload)

        # 读回来核对：zip 完整、三个成员都在、行数对得上
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = sorted(archive.namelist())
            truth_lines = archive.read("truth.csv").decode().strip().splitlines()
            obs_lines = archive.read("observations.csv").decode().strip().splitlines()

        print(f"{name}")
        print(f"  大小      : {len(payload):,} 字节")
        print(f"  成员      : {', '.join(members)}")
        print(f"  truth     : {len(truth_lines) - 1} 行数据 = {len(targets)} 目标 × {steps} 步")
        print(f"  observations: {len(obs_lines) - 1} 行")
        print(f"  配置要设  : 目标数 = {len(targets)}，时间步数 ≤ {steps}")
        print(f"  起点      : " + " / ".join(f"({t['x0']:.0f}, {t['y0']:.0f})" for t in targets[:4])
              + (" ..." if len(targets) > 4 else ""))
        print()

    print(f"输出目录：{out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
