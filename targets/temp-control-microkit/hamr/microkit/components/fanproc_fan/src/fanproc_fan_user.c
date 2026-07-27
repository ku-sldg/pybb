#include "fanproc_fan.h"

// This file will not be overwritten if HAMR codegen is rerun

void fanproc_fan_initialize(void) {
  printf("%s: fanproc_fan_initialize invoked\n", microkit_name);
}

void fanproc_fan_timeTriggered(void) {
  printf("%s: fanproc_fan_timeTriggered invoked\n", microkit_name);
}

void fanproc_fan_notify(microkit_channel channel) {
  // this method is called when the monitor does not handle the passed in channel
  switch (channel) {
    default:
      printf("%s: Unexpected channel %d\n", microkit_name, channel);
  }
}
