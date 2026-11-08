"""A FABRICATED exposed camera for the checker's stdlib tests: the goal at the world origin projects
to (row 150, column 350), one metre in front of the camera, with a projected radius of about
11.28 px, so a 400-pixel green disc there is the whole goal (v_g about 1.0). No simulator."""

from __future__ import annotations

import math

GOAL_POSITION = [0.0, 0.0, 0.0]
FOCAL_PX = 11.284 / math.tan(math.asin(0.0125 * 1.25 / 1.0))
CAMERA = {
    "exposed": True,
    "intrinsic_cv": [[FOCAL_PX, 0.0, 350.0], [0.0, FOCAL_PX, 150.0], [0.0, 0.0, 1.0]],
    "extrinsic_cv": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0]],
    "cam2world_gl": [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, -1.0],
        [0, 0, 0, 1],
    ],
}
GOAL = ((150.0, 350.0), 11.284)
SHIFTS = ((0, 22), (22, 0), (0, -22), (-22, 0), (16, 16))  # whole-pixel 0.03 m shifts, made up
