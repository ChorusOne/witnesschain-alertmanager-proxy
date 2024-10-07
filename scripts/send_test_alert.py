import argparse
import copy

import requests


parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument(
    "--watchtower-id", default="0x0e71247b49013664006D8472107f9e127695d9d7"
)
parser.add_argument("--timestamp", default="Oct 7 14:26:18 2024")
parser.add_argument("--file", default="emulator.py")
parser.add_argument("--line", default="9393")
parser.add_argument("--message", default="This is a test alert message")


def main(url: str, **labels: str) -> None:
    """
    message := fmt.Sprintf("watchtower_id: %v\nfrom: %v\ntimestamp: %v\nfile: %v\nline: %vmessage: %v\n", simpleConfig.WatchtowerAddress, from, now, file, line, fatalErrorMessageString)

    request, _ := json.Marshal(map[string] interface{}{
        "text": message,
    })

    requestBody := bytes.NewBuffer(request)
    """
    msg = ""
    for k, v in labels.items():
        msg += f"{k}: {v}"
        msg += "\n"
    requests.post(url, json={"text": msg})


if __name__ == "__main__":
    args = parser.parse_args()
    d = copy.deepcopy(args.__dict__)
    url = d.pop("url")
    main(url, **d)
