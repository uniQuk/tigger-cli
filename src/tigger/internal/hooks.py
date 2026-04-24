# Tigger Internal Hooks
#
# This file provides bundled default hooks. It is loaded only when
# no project-level or user-global hooks.py exists.
#
# To customize hooks, create .tigger/hooks.py in your project or
# ~/.tigger/hooks.py for global hooks. Your file fully replaces this one.
#
# Hook API:
#   from tigger.hooks import on_before, on_after
#
#   @on_before("bash")
#   def my_hook(call, ctx):
#       # modify call.args before execution
#       return call
#
#   @on_after("bash")
#   def my_after_hook(event, ctx):
#       # inspect or modify event after execution
#       return event
