#include "tsproc_tempSensor.h"

// This file will not be overwritten if HAMR codegen is rerun

void tsproc_tempSensor_initialize(void) {
  printf("%s: tsproc_tempSensor_initialize invoked\n", microkit_name);
}

void tsproc_tempSensor_timeTriggered(void) {
  printf("%s: tsproc_tempSensor_timeTriggered invoked\n", microkit_name);
}

void tsproc_tempSensor_notify(microkit_channel channel) {
  // this method is called when the monitor does not handle the passed in channel
  switch (channel) {
    default:
      printf("%s: Unexpected channel %d\n", microkit_name, channel);
  }
}
