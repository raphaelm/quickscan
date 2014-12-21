#!/usr/bin/env python
from blessings import Terminal
import os
import sys
import tty
import termios
import tempfile
import subprocess
from datetime import datetime
from queue import Queue
from threading import Thread

DEVICE = "fujitsu:ScanSnap iX500:68810"
SCANIMAGE = "scanimage"
CUSTOM_SCANIMAGE_SETTINGS = [
    '--page-height', '300mm', '-y', '300mm',
    '--brightness', '10',
    '--contrast', '10',
]
TESSERACT = "tesseract"
CUSTOM_TESSERACT_SETTINGS = ['-l', 'deu+eng']
GHOSTSCRIPT = "gs"
PAGESIZE = (842, 595)  # A4
IMAGEMAGICK_CONVERT = "convert"
CUSTOM_CONVERT_SETTINGS = ['-page', 'A4']
THREADS = 4

t = Terminal()


def getch():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None


def input_string(text, prompt, default=None):
    while True:
        print()
        print(text)
        if default:
            print(t.bold(prompt) + " " + t.cyan("[%s]" % default), end=": ")
        else:
            print(t.bold(prompt), end=": ")
        inp = input().strip()
        if inp == "":
            if default:
                return default
            print(t.bold_red('Input is required.'))
        else:
            return inp


def input_number(text, prompt, default=None):
    while True:
        print()
        print(text)
        if default:
            print(t.bold(prompt) + " " + t.cyan("[%d]" % default), end=": ")
        else:
            print(t.bold(prompt), end=": ")
        inp = input().strip()
        if inp == "":
            if default:
                return default
            print(t.bold_red('Input is required.'))
        else:
            try:
                return int(inp)
            except:
                print(t.bold_red('Input must be an integer.'))


def input_selection(text, prompt, selection, default=None):
    while True:
        print()
        print(text)
        for k, v in selection.items():
            print("[%s] %s" % (k, v))
        if default:
            print(t.bold(prompt) + " " + t.cyan("[%s]" % default), end=": ")
        else:
            print(t.bold(prompt), end=": ")
        sys.stdout.flush()
        inp = getch()
        print(inp)
        if inp.strip() == "" and default:
            return default
        if inp in selection:
            return selection[inp]
        elif inp == "q":
            sys.exit(0)
        else:
            print(t.bold_red('Input must be one of the available options.'))


def worker():
    while True:
        f = q.get()
        ocrfile = 'tmp%000d' % num(f)
        outfile = 'out%000d.pdf' % num(f)
        tesserargs = [TESSERACT]
        tesserargs += CUSTOM_TESSERACT_SETTINGS
        tesserargs += [
            f, ocrfile,
            'pdf'
        ]
        print(" ".join(tesserargs))
        subprocess.call(tesserargs)
        gsargs = [
            GHOSTSCRIPT,
            '-q', '-dNOPAUSE', '-dBATCH', '-sDEVICE=pdfwrite',
            '-dDEVICEWIDTHPOINTS=%d' % PAGESIZE[0],
            '-dDEVICEHEIGHTPOINTS=%d' % PAGESIZE[1],
            '-dPDFFitPage',
            '-o', outfile,
            '%s.pdf' % ocrfile
        ]
        print(" ".join(gsargs))
        subprocess.call(gsargs)
        q.task_done()

if not which(SCANIMAGE):
    print(t.bold_red('scanimage command not found.'))
    sys.exit(1)

if not which(TESSERACT):
    print(t.bold_red('tesseract command not found.'))
    sys.exit(2)

if not which(GHOSTSCRIPT):
    print(t.bold_red('gs command not found.'))
    sys.exit(2)

print("Hi there!")

mode = input_selection(
    'Scan in color or grayscale?',
    'Mode',
    {'g': 'Gray', 'c': 'Color'},
    'g'
)

ocr = (input_selection(
    'Perform OCR?',
    'OCR',
    {'y': 'Yes', 'n': 'No'},
    'n'
) == 'Yes')

default_dpi = 300 if ocr else (150 if mode == 'Color' else 200)

dpi = input_number(
    'Specify the scan resolution',
    'DPI', default_dpi
)

source = "ADF Duplex" if (input_selection(
    'Scan in duplex mode?',
    'ADF Duplex',
    {'y': 'Yes', 'n': 'No'},
    'n'
) == 'Yes') else "ADF Front"

pages = input_number(
    'How many pages? A duplex page counts as two.',
    'Page count',
    -1
)

if sys.argc < 2:
    catfile = os.path.abspath(input_string(
        'Output filename',
        'Filename',
        'scan-%s.pdf' % datetime.now().strftime('%Y-%m-%d-%H-%M')
    ))
else:
    catfile = sys.argv[1]

scanargs = [
    SCANIMAGE,
    '-d', DEVICE,
    '--batch-start', '1',
    '--batch-count', str(pages),
    '--mode', mode,
    '--resolution', str(dpi) + 'dpi',
    '--batch=out%d.pnm',
    '--source', source,
] + CUSTOM_SCANIMAGE_SETTINGS

q = Queue()
num = lambda f: int(f.replace("out", "").replace(".pnm", ""))

with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    print(" ".join(scanargs))
    while True:
        if subprocess.call(scanargs) == 0:
            break
        else:
            if input_selection(
                t.bold_red('scanimage returned non-zero status code. Repeat scan?'),
                'Repeat?',
                {'y': 'Yes', 'n': 'No'},
                'n'
            ) == 'No':
                break

    pdfs = []
    if ocr:
        for i in range(THREADS):
            th = Thread(target=worker)
            th.daemon = True
            th.start()

        ignore = input_string(
            'Ignore some pages? Seperate numbers (starting at 1) with commas',
            'Pages to ignore', ''
        ).split(",")
        for i, f in enumerate(sorted([f for f in os.listdir() if f.endswith(".pnm")], key=num)):
            if str(i + 1) not in ignore:
                outfile = 'out%000d.pdf' % num(f)
                q.put(f)
                pdfs.append(outfile)

        q.join()
        gsargs = [
            GHOSTSCRIPT,
            '-q', '-dNOPAUSE', '-dBATCH', '-sDEVICE=pdfwrite',
            '-sOutputFile=%s' % catfile,
        ] + pdfs
        print(" ".join(gsargs))
        subprocess.call(gsargs)
    else:
        convertargs = [IMAGEMAGICK_CONVERT] + CUSTOM_CONVERT_SETTINGS
        ignore = input_string(
            'Ignore some pages? Seperate numbers (starting at 1) with commas',
            'Pages to ignore', ''
        ).split(",")
        pnms = [f for i, f in enumerate(sorted([f for f in os.listdir() if f.endswith(".pnm")], key=num)) if str(i + 1) not in ignore]
        convertargs += sorted(pnms, key=num)
        convertargs.append(catfile)
        print(" ".join(convertargs))
        subprocess.call(convertargs)
