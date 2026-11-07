"""Forward and inverse kinematics of the simulated SO-100, in pure Python.

Joint values are in rad, in the order shoulder_pan, shoulder_lift, elbow_flex, wrist_flex,
wrist_roll, gripper. Positions are in metres in the world frame. The chain and the base pose come
from the ``mani_skill`` 3.0.1 URDF and its PickCube scene; a test checks them against values read
from the running simulator. ``mplib``, which ManiSkill's own planner uses, is Linux-only.

Solving failures are returned as ``None``, and nothing here commands a robot.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Matrix = list[list[float]]
Vector = tuple[float, float, float]

BASE_POSITION = (-0.725, 0.0, 0.0)
BASE_YAW = math.pi / 2
ARM_JOINTS = 4  # shoulder_pan, shoulder_lift, elbow_flex and wrist_flex position the tool.

# (origin xyz, origin rpy, joint axis index and sign) from the URDF, in chain order.
_CHAIN: tuple[tuple[Vector, Vector, tuple[int, float]], ...] = (
    ((0.0, -0.0452, 0.0165), (1.5708, 0.0, 0.0), (1, -1.0)),
    ((0.0, 0.1025, 0.0306), (0.0, 0.0, 0.0), (0, 1.0)),
    ((0.0, 0.11257, 0.028), (0.0, 0.0, 0.0), (0, 1.0)),
    ((0.0, 0.0052, 0.1349), (-1.5708, 0.0, 0.0), (0, 1.0)),
    ((0.0, -0.0601, 0.0), (0.0, 1.5708, 0.0), (1, 1.0)),
)
_GRIPPER_ORIGIN: tuple[Vector, Vector] = ((-0.0202, -0.0244, 0.0), (0.0, 3.14159, -0.9))
_FIXED_TIP: Vector = (0.01, -0.097, 0.0)
_MOVING_TIP: Vector = (-0.01, -0.073, 0.0)


def _rotation(rpy: Vector) -> Matrix:
    roll, pitch, yaw = rpy
    sr, cr = math.sin(roll), math.cos(roll)
    sp, cp = math.sin(pitch), math.cos(pitch)
    sy, cy = math.sin(yaw), math.cos(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


def _axis_rotation(axis: int, angle: float) -> Matrix:
    rpy = [0.0, 0.0, 0.0]
    rpy[axis] = angle
    return _rotation((rpy[0], rpy[1], rpy[2]))


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def _apply(rotation: Matrix, v: Vector) -> Vector:
    return (
        rotation[0][0] * v[0] + rotation[0][1] * v[1] + rotation[0][2] * v[2],
        rotation[1][0] * v[0] + rotation[1][1] * v[1] + rotation[1][2] * v[2],
        rotation[2][0] * v[0] + rotation[2][1] * v[1] + rotation[2][2] * v[2],
    )


def _add(a: Vector, b: Vector) -> Vector:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _wrist_frame(joints: Sequence[float]) -> tuple[Vector, Matrix]:
    """World position and rotation of the fixed jaw's frame."""
    position = BASE_POSITION
    rotation = _rotation((0.0, 0.0, BASE_YAW))
    for (origin, rpy, (axis, sign)), angle in zip(_CHAIN, joints[:5], strict=True):
        position = _add(position, _apply(rotation, origin))
        rotation = _multiply(
            _multiply(rotation, _rotation(rpy)), _axis_rotation(axis, sign * angle)
        )
    return position, rotation


def fingertips(joints: Sequence[float]) -> tuple[Vector, Vector]:
    """World positions of the fixed and moving jaw tips, for all six joints."""
    position, rotation = _wrist_frame(joints)
    fixed = _add(position, _apply(rotation, _FIXED_TIP))
    origin, rpy = _GRIPPER_ORIGIN
    moving_position = _add(position, _apply(rotation, origin))
    moving_rotation = _multiply(_multiply(rotation, _rotation(rpy)), _axis_rotation(2, joints[5]))
    moving = _add(moving_position, _apply(moving_rotation, _MOVING_TIP))
    return fixed, moving


def arm_segments(joints: Sequence[float]) -> list[tuple[Vector, Vector]]:
    """The arm as line segments in the world frame, for all six joints: base to each joint origin
    in chain order to the fixed jaw's frame, then that frame to the fixed jaw tip, and through the
    moving jaw's origin to its tip. A skeleton, without the links' thickness."""
    points = [BASE_POSITION]
    position = BASE_POSITION
    rotation = _rotation((0.0, 0.0, BASE_YAW))
    for (origin, rpy, (axis, sign)), angle in zip(_CHAIN, joints[:5], strict=True):
        position = _add(position, _apply(rotation, origin))
        points.append(position)
        rotation = _multiply(
            _multiply(rotation, _rotation(rpy)), _axis_rotation(axis, sign * angle)
        )
    fixed, moving = fingertips(joints)
    moving_origin = _add(position, _apply(rotation, _GRIPPER_ORIGIN[0]))
    chain = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    return [*chain, (position, fixed), (position, moving_origin), (moving_origin, moving)]


def segment_distance(p1: Vector, q1: Vector, p2: Vector, q2: Vector) -> float:
    """The shortest distance between segments p1-q1 and p2-q2 (Ericson, Real-Time Collision
    Detection, section 5.1.9)."""
    d1 = (q1[0] - p1[0], q1[1] - p1[1], q1[2] - p1[2])
    d2 = (q2[0] - p2[0], q2[1] - p2[1], q2[2] - p2[2])
    r = (p1[0] - p2[0], p1[1] - p2[1], p1[2] - p2[2])

    def dot(u: Vector, v: Vector) -> float:
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    def clamp(value: float) -> float:
        return min(max(value, 0.0), 1.0)

    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    eps = 1e-15
    if a <= eps and e <= eps:
        s = t = 0.0
    elif a <= eps:
        s, t = 0.0, clamp(f / e)
    else:
        c = dot(d1, r)
        if e <= eps:
            s, t = clamp(-c / a), 0.0
        else:
            b = dot(d1, d2)
            denominator = a * e - b * b
            s = clamp((b * f - c * e) / denominator) if denominator > eps else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                s, t = clamp(-c / a), 0.0
            elif t > 1.0:
                s, t = clamp((b - c) / a), 1.0
    closest1 = (p1[0] + d1[0] * s, p1[1] + d1[1] * s, p1[2] + d1[2] * s)
    closest2 = (p2[0] + d2[0] * t, p2[1] + d2[1] * t, p2[2] + d2[2] * t)
    return math.dist(closest1, closest2)


def tool_point(joints: Sequence[float]) -> Vector:
    """The midpoint between the jaw tips, which ManiSkill calls the TCP."""
    fixed, moving = fingertips(joints)
    return ((fixed[0] + moving[0]) / 2, (fixed[1] + moving[1]) / 2, (fixed[2] + moving[2]) / 2)


def approach_direction(joints: Sequence[float]) -> Vector:
    """The unit direction of the wrist-roll axis, pointing from the wrist towards the jaws.

    This axis stays in the arm's vertical plane whatever the roll, so three position constraints
    and this one tilt can all be met by the four arm joints.
    """
    _, rotation = _wrist_frame(joints)
    return _apply(rotation, (0.0, -1.0, 0.0))


def jaw_direction(joints: Sequence[float]) -> Vector:
    """The unit direction from the fixed jaw tip to the moving jaw tip."""
    fixed, moving = fingertips(joints)
    gap = math.dist(fixed, moving)
    if gap == 0.0:
        raise ValueError("the jaw tips coincide")
    return (
        (moving[0] - fixed[0]) / gap,
        (moving[1] - fixed[1]) / gap,
        (moving[2] - fixed[2]) / gap,
    )


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; ``None`` if the matrix is singular."""
    size = len(vector)
    rows = [[*row, value] for row, value in zip(matrix, vector, strict=True)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for row in range(col + 1, size):
            factor = rows[row][col] / rows[col][col]
            for k in range(col, size + 1):
                rows[row][k] -= factor * rows[col][k]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        known = sum(rows[row][k] * solution[k] for k in range(row + 1, size))
        solution[row] = (rows[row][size] - known) / rows[row][row]
    return solution


def _converged(
    joints: list[float], target: Vector, tolerance_m: float, tilt_tolerance: float
) -> bool:
    """Is the tool at the target, with the jaws pointing down and not up?"""
    direction = approach_direction(joints)
    return (
        math.dist(tool_point(joints), target) <= tolerance_m
        and math.hypot(direction[0], direction[1]) <= tilt_tolerance
        and direction[2] < 0.0
    )


def _residual(joints: list[float], target: Vector, down_weight: float) -> list[float]:
    point = tool_point(joints)
    direction = approach_direction(joints)
    return [
        target[0] - point[0],
        target[1] - point[1],
        target[2] - point[2],
        -direction[0] * down_weight,
        -direction[1] * down_weight,
    ]


def solve_tool_down(
    target: Vector,
    seed: Sequence[float],
    *,
    limits: Sequence[tuple[float, float]],
    down_weight: float = 0.05,
    tolerance_m: float = 0.0005,
    tilt_tolerance: float = 0.02,
    max_iterations: int = 200,
) -> list[float] | None:
    """Find joints that put the tool point at ``target`` with the jaws pointing straight down.

    Only the first four joints move; roll and gripper stay at ``seed``. Damped least squares on a
    numeric Jacobian, kept within ``limits``. Returns ``None`` unless the position error is within
    ``tolerance_m`` and the sine of the tilt from vertical is within ``tilt_tolerance``.
    """
    joints = list(seed)
    step = 1e-5
    damping = 1e-4
    for _ in range(max_iterations):
        if _converged(joints, target, tolerance_m, tilt_tolerance):
            return joints
        residual = _residual(joints, target, down_weight)
        columns: list[list[float]] = []
        for index in range(ARM_JOINTS):
            moved = list(joints)
            moved[index] += step
            after = _residual(moved, target, down_weight)
            columns.append([(a - b) / step for a, b in zip(after, residual, strict=True)])
        normal = [
            [
                sum(columns[r][k] * columns[c][k] for k in range(len(residual)))
                + (damping if r == c else 0.0)
                for c in range(ARM_JOINTS)
            ]
            for r in range(ARM_JOINTS)
        ]
        rhs = [
            -sum(columns[r][k] * residual[k] for k in range(len(residual)))
            for r in range(ARM_JOINTS)
        ]
        update = _solve(normal, rhs)
        if update is None:
            return None
        for index in range(ARM_JOINTS):
            low, high = limits[index]
            joints[index] = min(high, max(low, joints[index] + update[index]))
    return joints if _converged(joints, target, tolerance_m, tilt_tolerance) else None
