// This file will not be overwritten if HAMR codegen is rerun

use data::*;
use crate::bridge::tsproc_tempSensor_api::*;
use vstd::prelude::*;

verus! {

  pub struct tsproc_tempSensor {
    // PLACEHOLDER MARKER STATE VARS
  }

  impl tsproc_tempSensor {
    pub fn new() -> Self
    {
      Self {
        // PLACEHOLDER MARKER STATE VAR INIT
      }
    }

    pub fn initialize<API: tsproc_tempSensor_Put_Api> (
      &mut self,
      api: &mut tsproc_tempSensor_Application_Api<API>)
      ensures
        // BEGIN MARKER INITIALIZATION ENSURES
        // guarantee currentTempInitialVal
        api.currentTemp.degrees == 72i32,
        // END MARKER INITIALIZATION ENSURES
    {
      log_info("initialize entrypoint invoked");
    }

    pub fn timeTriggered<API: tsproc_tempSensor_Full_Api> (
      &mut self,
      api: &mut tsproc_tempSensor_Application_Api<API>)
      requires
        // PLACEHOLDER MARKER TIME TRIGGERED REQUIRES
      ensures
        // PLACEHOLDER MARKER TIME TRIGGERED ENSURES
    {
      log_info("compute entrypoint invoked");
    }

    pub fn notify(
      &mut self,
      channel: microkit_channel)
    {
      // this method is called when the monitor does not handle the passed in channel
      match channel {
        _ => {
          log_warn_channel(channel)
        }
      }
    }
  }

  #[verifier::external_body]
  pub fn log_info(msg: &str)
  {
    log::info!("{0}", msg);
  }

  #[verifier::external_body]
  pub fn log_warn_channel(channel: u32)
  {
    log::warn!("Unexpected channel: {0}", channel);
  }

  // PLACEHOLDER MARKER GUMBO METHODS

}
