# Re-record with: vhs docs/demo.tape  (reads the real local logs of whoever runs it; --public scrubs paths and names)
Output docs/demo.gif
Set Shell bash
Set FontSize 14
Set Width 1640
Set Height 600
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Hide
Type "export PS1='$ ' PATH=$PWD/.venv/bin:$PATH && clear"
Enter
Show
Sleep 600ms
Type "orchestra-review --public --top 6"
Sleep 400ms
Enter
Sleep 7s
