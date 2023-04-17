# NumWorksFS
A FUSE to access the files from your NumWorks calculator right from the explorer

## Prerequisite
This program uses [upsilon-py](https://pypi.org/project/upsilon-py/), which means it also carries the same requirements. These are:  
- Have a working [Node](https://nodejs.org/) installation with [NPM](https://www.npmjs.com/)  
- Have upsilon.js installed. You can use the command `npm install -g "upsilon.js@^1.4.1" usb`  

You must also:
- Install the requirements: `pip install -r requirements.txt`

## Usage
The simplest usage is simply:  
`python3 ./run.py "/path/to/mount"`  

Then, when you're done:
`umount "/path/to/mount"`

To see the other options, simply run `python ./run.py --help`

## Issues
Due to how upsilon-py works, it's impossible to setup automatic reconnection. Therefore, **the FUSE is automatically closed during the first operations that's done after the calculator is unplugged.** 

If you're interested as to why it's impossible, it's that the call to numworks.connect() is blocking, and it cannot be threaded or upsilon-py starts breaking down.  
It would *technically* be possible to just wait for numworks.connect(), but that would mean entirely blocking IO as soon as the calculator is disconnected, which will most likely lead to your file explorer freezing until the calculator is plugged back in.


## Licence
GNU General Public License version 2 (or later, at your option)