*************************
FogLAMP South systeminfo
*************************

This directory contains a South plugin that fetches System Info at defined intervals.

**Known issues:**

- For now this debian works with default configuration, it does not work if the Admin API config gets:

      1. host, port, https scheme changes

      2. authentication as mandatory

      3. authentication as mandatory & allowPing as false
