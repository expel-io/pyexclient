<br />
<p align="center">
  <h3 align="center">Pyexclient</h3>

  <p align="center">
    A Python client for the Expel Workbench.
    <br />
    <a href="https://pyexclient.readthedocs.io"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/expel-io/pyexclient/issues">Report Bug</a>
    ·
    <a href="https://github.com/expel-io/pyexclient/issues">Request Feature</a>
    ·
    <a href="https://expel.io">Expel.io</a>
  </p>
</p>


<!-- TABLE OF CONTENTS -->
## Table of Contents

* [About the Project](#about-the-project)
* [Getting Started](#getting-started)
  * [Prerequisites](#prerequisites)
  * [Installation](#installation)
* [Usage](#usage)
* [Reporting a bug / Filing a Feature Request](#issues)
* [Contributing](#contributing)
* [License](#license)


<!-- ABOUT THE PROJECT -->
## About The Project

Pyexclient is a Python client for the Expel Workbench. If you can click it in the UI, you can also automate it with our APIs. Want to build a custom report? Integrate Expel Workbench with your SOAR platform? Pyexclient can help you acommplish that and more!


<!-- GETTING STARTED -->
## Getting Started

To get up and running follow these simple steps.

### Prerequisites

Pyexclient requires `python>=3.7`.

### Installation

To install Pyexclient, use pip.

```sh
pip install pyexclient
```


<!-- USAGE EXAMPLES -->
## Usage

You can get started with Pyexclient in two easy steps:

**Step 1: Authenticate to Workbench**

You can authenticate with your Expel Workbench credentials:
```py
import getpass
from pyexclient import WorkbenchClient

wb = WorkbenchClient(
        'https://workbench.expel.io',
        username=input("Username: "),
        password=getpass.getpass("Password: ",
        mfa_code=input("MFA Code: ")
    )
```

Alternatively, you can authenticate with an API key (useful for long running scripts). Contact your Expel Engagement Manager to request an API key.
```py
import getpass
from pyexclient import WorkbenchClient

wb = WorkbenchClient(
        'https://workbench.expel.io',
        apikey=getpass.getpass("API Key: ")
    )
```

**Step 2: Start Exploring!**

In the example below, we're printing investigations:
```py

for inv in wb.investigations:
    print(inv)
```

_For more examples (we have a ton!), please refer to the [Documentation](https://pyexclient.readthedocs.io). As a starting point, check out [Code Snippets](READTHEDOCS) and [Example Scripts](READTHEDOCS)._


<!-- ISSUES -->
## Issues

If you find a bug or have an idea for the next amazing feature, please [create an issue](https://github.com/expel-io/pyexclient/issues). We'll get back to you as soon as we can!


<!-- CONTRIBUTING -->
## Contributing

Contributions are welcome!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request


<!-- LICENSE -->
## License

Distributed under the BSD 2-Clause License. See `LICENSE` for more information.

