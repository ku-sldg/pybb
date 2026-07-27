// This file will not be overwritten if HAMR codegen is rerun

use data::*;
use crate::bridge::tcproc_tempControl_api::*;
use vstd::prelude::*;

verus! {

  pub struct tcproc_tempControl {
    // BEGIN MARKER STATE VARS
    pub latestFanCmd: CoolingFan::FanCmd,
    // END MARKER STATE VARS
  }

  impl tcproc_tempControl {
    pub fn new() -> Self
    {
      Self {
        // BEGIN MARKER STATE VAR INIT
        latestFanCmd: CoolingFan::FanCmd::default(),
        // END MARKER STATE VAR INIT
      }
    }

    pub fn initialize<API: tcproc_tempControl_Put_Api> (
      &mut self,
      api: &mut tcproc_tempControl_Application_Api<API>)
      ensures
        // BEGIN MARKER INITIALIZATION ENSURES
        // guarantee initLatestFanCmd
        //   Initialize state variable
        self.latestFanCmd == CoolingFan::FanCmd::Off,
        // guarantee initFanCmd
        //   Initial fan command
        api.fanCmd == CoolingFan::FanCmd::Off,
        // END MARKER INITIALIZATION ENSURES
    {
      log_info("initialize entrypoint invoked");
      self.latestFanCmd = CoolingFan::FanCmd::Off;
      api.put_fanCmd(CoolingFan::FanCmd::Off);
    }

    pub fn timeTriggered<API: tcproc_tempControl_Full_Api> (
      &mut self,
      api: &mut tcproc_tempControl_Application_Api<API>)
      requires
        // BEGIN MARKER TIME TRIGGERED REQUIRES
        // assume validSetPoint
        //   set point range is well-formed
        old(api).setPoint.low.degrees < old(api).setPoint.high.degrees,
        // END MARKER TIME TRIGGERED REQUIRES
      ensures
        // BEGIN MARKER TIME TRIGGERED ENSURES
        // guarantee altCurrentTempLTSetPoint
        //   If current temperature is less than
        //   the current low set point, then the fan state shall be Off
        (api.currentTemp.degrees < api.setPoint.low.degrees) ==>
          (self.latestFanCmd == CoolingFan::FanCmd::Off) &&
            (api.fanCmd == CoolingFan::FanCmd::Off),
        // guarantee altCurrentTempGTSetPoint
        //   If current temperature is greater than
        //   the current high set point, then the fan state shall be On
        (api.currentTemp.degrees > api.setPoint.high.degrees) ==>
          ((self.latestFanCmd == CoolingFan::FanCmd::On) &&
            (api.fanCmd == CoolingFan::FanCmd::On)),
        // guarantee altCurrentTempInRange
        //   If current temperature is greater than or equal to the 
        //   current low set point and less than or equal to the current high set point, 
        //   then the current fan state is maintained.
        ((api.currentTemp.degrees >= api.setPoint.low.degrees) &&
          (api.currentTemp.degrees <= api.setPoint.high.degrees)) ==>
          ((self.latestFanCmd == old(self).latestFanCmd) &&
            (api.fanCmd == self.latestFanCmd)),
        // END MARKER TIME TRIGGERED ENSURES
    {
      log_info("compute entrypoint invoked");
      let currentTemp = api.get_currentTemp();
      let setPoint = api.get_setPoint();
      let newCmd = if currentTemp.degrees < setPoint.low.degrees {
        CoolingFan::FanCmd::Off
      } else if currentTemp.degrees > setPoint.high.degrees {
        CoolingFan::FanCmd::On
      } else {
        self.latestFanCmd
      };
      self.latestFanCmd = newCmd;
      api.put_fanCmd(newCmd);
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
