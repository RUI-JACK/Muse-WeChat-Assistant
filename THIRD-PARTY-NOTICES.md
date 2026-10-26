# Third-party notices

The installer contains CPython with Tcl/Tk, UIAutomation for Python, comtypes, Pillow, pywin32, typing-extensions, and PyWinRT projections/runtime. Their versions are pinned in `requirements.txt` (Python 3.11.16). Original copyright and license texts extracted from their distributions are included in `third-party-licenses` inside the installation.

Microsoft Visual C++ Redistributable is supplied as Microsoft's digitally signed original installer and remains subject to Microsoft's terms. Windows OCR is an operating system component installed through Windows servicing when requested; it is not reimplemented or redistributed as a copied system DLL.

The installer is generated with Inno Setup 6.7.3. Source and documentation: https://jrsoftware.org/isinfo.php . Windows runtime documentation: https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist . Python runtime: https://www.python.org/ . PyWinRT: https://github.com/pywinrt/pywinrt . The build runtime is a complete CPython distribution; the original Python license is included.

The Simplified Chinese installer translation in `packaging/ChineseSimplified.isl` is from the Inno Setup source repository, maintained by Zhenghan Yang (Kira). Its original attribution header is preserved.

WeChat, Muse, Chrome and Microsoft Edge are not included in the distribution. Users install and log in to these products themselves. No account credentials or chat histories are distributed.
