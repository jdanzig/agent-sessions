# agent-sessions

A small self-hosted web dashboard for launching coding-agent sessions on a remote machine from your phone. It lists your project folders, makes new ones, and starts, resumes, or kills a headless Claude Code session in any of them. You steer the session from the Claude app or claude.ai/code. No terminal, no SSH client, no cloud relay.

I built it because SSHing into an always-on machine from a phone is miserable.

## What it does

- Lists the project folders under a base directory (`~/code`), newest first, with a live indicator on any folder that has a running session.
- Creates a new folder.
- Starts or resumes a Claude Code Remote Control session in a folder (`claude remote-control -c`), running headless in its own tmux session.
- Kills a session.

Phone-first: tap a folder, a session spins up on the machine, and you drive it from the Claude app.

## The setup it runs in

This is one piece of a remote-work setup built on Tailscale.

**Execution node.** An always-on Mac mini runs the long jobs: agent sessions, builds, renders. The phone is just a remote.

**Private access over Tailscale.** The dashboard binds locally and is reachable only over the tailnet. No public port, no inbound firewall hole, no third-party relay. From a phone on cellular it is just `http://<tailscale-name>:8485`.

**Headless sessions in tmux.** Each folder's session runs detached in tmux, so it survives the page closing and keeps running while you are away. It uses a dedicated tmux socket so the session is spawned by the LaunchAgent's GUI login session, which is what lets `claude remote-control` read its OAuth item from the keychain.

**Delivery back to the phone with Taildrop.** When a job produces a file, `tailscale file cp` drops it straight onto the phone or laptop. No upload, no cloud, no link to paste.

The result is a loop that runs entirely from the phone: kick off work, it runs on the mini, the result comes back, no laptop in between.

## Requirements

- macOS (the always-on setup uses `launchd`; the server itself is plain Python).
- Python 3, standard library only, no dependencies.
- `tmux`.
- The [Claude Code](https://claude.com/claude-code) CLI, installed and logged in (`claude`). Sessions are started with `claude remote-control`.
- [Tailscale](https://tailscale.com) on the host and your phone, to reach the dashboard remotely. On the same Wi-Fi you can skip it and use the host's LAN IP.

## Running it

```
python3 agent-sessions.py          # serves ~/code on http://0.0.0.0:8485
```

Point it at a different base directory, or run a second instance on another port:

```
python3 agent-sessions.py ~/clips 8486
```

### Always-on (macOS LaunchAgent)

Copy the template, fill in your home path, and load it:

```
cp agent-sessions.plist.template ~/Library/LaunchAgents/com.example.agent-sessions.plist
# edit the two /Users/... paths inside
launchctl load ~/Library/LaunchAgents/com.example.agent-sessions.plist
```

`KeepAlive` keeps it running; it reloads itself when the source file changes. Logs go to `/tmp/agent-sessions.log`.

## Notes

- Stateless. The folders on disk are the only state.
- The HTML is served from `agent-sessions.html` and re-read on every request, so UI edits are live without a restart.
- Reachable only on your tailnet. Do not expose the port publicly: it can start processes on your machine.

## Scope and limitations

- **macOS only** for the always-on install (`launchd`). The server is portable Python; the install flow is Mac-specific.
- **No auth.** The tailnet is the security boundary. Anyone who can reach the port can list folders and start a session, so do not expose it beyond your tailnet or LAN.
- **Single machine, single user.** It runs sessions on the host it is installed on. No remotes, no multi-user.
- **Claude Code only.** It shells out to `claude remote-control`; another agent would need its own launch command.
