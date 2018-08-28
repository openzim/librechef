# LibreTexts Chef

Kolibri is an open source educational platform to distribute content to areas with
little or no internet connectivity. Educational content is created and edited on [Kolibri Studio](https://studio.learningequality.org),
which is a platform for organizing content to import from the Kolibri applications. The purpose
of this project is to create a *chef*, or a program that scrapes a content source and puts it
into a format that can be imported into Kolibri Studio. 


## Installation

* Install [Python 3](https://www.python.org/downloads/) if you don't have it already.

* Install [pip](https://pypi.python.org/pypi/pip) if you don't have it already.

* Create a Python virtual environment for this project (optional, but recommended):
   * Install the virtualenv package: `pip install virtualenv`
   * The next steps depends if you're using UNIX (Mac/Linux) or Windows:
      * For UNIX systems:
         * Create a virtual env called `venv` in the current directory using the
           following command: `virtualenv -p python3  venv`
         * Activate the virtualenv called `venv` by running: `source venv/bin/activate`.
           Your command prompt will change to indicate you're working inside `venv`.
      * For Windows systems:
         * Create a virtual env called `venv` in the current directory using the
           following command: `virtualenv -p C:/Python36/python.exe venv`.
           You may need to adjust the `-p` argument depending on where your version
           of Python is located.
         * Activate the virtualenv called `venv` by running: `.\venv\Scripts\activate`

* Run `pip install -r requirements.txt` to install the required python libraries.




## Usage

TODO: Explain how to run the LibreTexts chef

      export SOMEVAR=someval
      ./script.py -v --option2 --kwoard="val"



## Description

A sushi chef script is responsible for importing content into Kolibri Studio.
The [Rice Cooker](https://github.com/learningequality/ricecooker) library provides
all the necessary methods for uploading the channel content to Kolibri Studio,
as well as helper functions and utilities.

A sushi chef script has been started for you in `sushichef.py`.

Sushi chef docs can be found [here](https://github.com/learningequality/ricecooker/blob/master/README.md).

_For more sushi chef examples, see `examples/openstax_sushichef.py` (json) and
 `examples/wikipedia_sushichef.py` (html) and also the examples/ dir inside the ricecooker repo._


---


## Rubric

_Please make sure your final chef matches the following standards._



#### General Standards
1. Does the code work (no infinite loops, exceptions thrown, etc.)?
1. Are the `source_id`s determined consistently (based on foreign database identifiers or permanent url paths)?
1. Is there documentation on how to run the script (include command line parameters to use)?

#### Coding Standards
1. Are there no obvious runtime or memory inefficiencies in the code?
1. Are the functions succinct?
1. Are clarifying comments provided where needed?
1. Are the git commits easy to understand?
1. Is there no unnecessary nested `if` or `for` loops?
1. Are variables named descriptively (e.g. `path` vs `p`)?

#### Python Standards
1. Is the code compatible with Python 3?
1. Does the code use common standard library functions where needed?
1. Does the code use common python idioms where needed (with/open, try/except, etc.)?

