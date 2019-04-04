# sushi-chef-sushi-chef-libretext
Sushi Chef script for importing sushi-chef-libretext content

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

     ./sushichef.py -v --reset --token=".token" --subject=chem
     ./sushichef.py -v --reset --token=".token" --subject=math
     ./sushichef.py -v --reset --token=".token" --subject=phys
     ./sushichef.py -v --reset --token=".token" --subject=eng
     ./sushichef.py -v --reset --token=".token" --subject=bio
     
## MathJax
MathJax files must be in a upper level folder i.e ../ or will raise an error. 
