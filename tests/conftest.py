# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
import pathlib
import sys

# Import `core` on its own: the integration package needs Home Assistant
sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'custom_components' / 'house_model'))
