How to use this project:
Documentation
- extensive documentation on the pdf and pptx files
- appunti.odt contains help to build a linux kernel, cpu isolation techniques, rt-app and other tools

Project tree (project)
- install opentelemetry in project/otel-installdir
- install rt-app in project/rt-app and replace files with given ones
- 2-DoE
	*-run: contains inputs/outputs for an experiment run
	data_table.csv: for reading input factor levels and writing response variables for a run
	index.txt: contains index of this run for data_table.csv
	
Scripts
- scripts/utils_isolation: scripts to isolate a cpu set
- scripts/measurements (test.sh: main script. Executes an experiment run and calls other scripts)

How to run an experiment:
- write levels for factors in a new row of the data table
- write row index in index.txt
- create a directory (e.g. DIR=2-DoE/1-first-examples/mydir)
- call test.sh $DIR. Experiment results will be written in $DIR

Note: scripts contain hardcoded values that you might need to change (e.g. duration of experiment, cpus where to run rt-app, ...)
