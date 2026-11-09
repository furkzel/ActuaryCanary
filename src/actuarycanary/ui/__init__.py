"""`canary ui`: a local browser interface over the same pipeline as the command line.

A small server of the standard library (bound to 127.0.0.1, every request carrying a random
token) serves one page and a JSON interface. The page lets a person choose a folder, look at
how the sheets were recognised and mapped, correct the mapping, run, and open the report. It
builds a `RunSettings` as `canary run` does and calls `pipeline.run` in a worker thread; it
keeps nothing outside memory and the output folder (records 0700 to 0706).
"""
