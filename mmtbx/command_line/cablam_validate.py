# LIBTBX_SET_DISPATCHER_NAME phenix.cablam_training

import sys
from mmtbx.cablam import cablam_validate

if __name__ == "__main__":
  cablam_validate.run([sys.argv[1:])
