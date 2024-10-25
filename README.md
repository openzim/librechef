# LibreTexts Chef

> [!WARNING]
> This fork was an attempt by openZIM / Kiwix to fix sushichef recipe for libretexts.org, in order to create a Kolibri channel from a libretexts.org library.
> It has finally been judged "better" to create our own scraper. This fork is hence "abandonned" as-is, and kept public only for further reference.
> Scraper for libretexts.org is available at https://github.com/openzim/mindtouch

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
* Note - In case you get import errors while running, you need to update numpy to the latest version, even if it gives an incompatability warning



## Usage

     ./sushichef.py -v --reset --token=".token" --subject=chem --channel-id=channelid
     ./sushichef.py -v --reset --token=".token" --subject=math --channel-id=channelid
     ./sushichef.py -v --reset --token=".token" --subject=phys --channel-id=channelid
     ./sushichef.py -v --reset --token=".token" --subject=eng --channel-id=channelid
     ./sushichef.py -v --reset --token=".token" --subject=bio --channel-id=channelid
     
## MathJax
MathJax files must be in a upper level folder i.e ../ or will raise an error. 

Version 2.7.5 should be used as-of Sept. 2024, and hence placed in ../MathJax-2.7.5
