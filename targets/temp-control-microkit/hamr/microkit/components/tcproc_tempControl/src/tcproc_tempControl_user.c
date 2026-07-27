#include "tcproc_tempControl.h"

// This file will not be overwritten if HAMR codegen is rerun

void tcproc_tempControl_initialize(void) {
  printf("%s: tcproc_tempControl_initialize invoked\n", microkit_name);
}

void tcproc_tempControl_timeTriggered(void) {
  printf("%s: tcproc_tempControl_timeTriggered invoked\n", microkit_name);
}

void tcproc_tempControl_notify(microkit_channel channel) {
  // this method is called when the monitor does not handle the passed in channel
  switch (channel) {
    default:
      printf("%s: Unexpected channel %d\n", microkit_name, channel);
  }
}
