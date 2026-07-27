#include "oiproc_operatorInterface.h"

// This file will not be overwritten if HAMR codegen is rerun

void oiproc_operatorInterface_initialize(void) {
  printf("%s: oiproc_operatorInterface_initialize invoked\n", microkit_name);
}

void oiproc_operatorInterface_timeTriggered(void) {
  printf("%s: oiproc_operatorInterface_timeTriggered invoked\n", microkit_name);
}

void oiproc_operatorInterface_notify(microkit_channel channel) {
  // this method is called when the monitor does not handle the passed in channel
  switch (channel) {
    default:
      printf("%s: Unexpected channel %d\n", microkit_name, channel);
  }
}
