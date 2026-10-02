# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Settings gunicorn picks up on its own from the directory it starts in.

Kept in a file rather than on the command line because the command line
lives in two places, the Dockerfile and the hosting service's start command,
and a flag added to one is missing from the other.
"""

# gunicorn 26 opens a control socket under $HOME by default. In a container
# the process often runs as an account without a home directory, and every
# start then logs "Control server error: Read-only file system". Nothing here
# uses that interface, so it stays off.
control_socket_disable = True
