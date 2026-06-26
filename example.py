from pybb import BlackboardController, NumberSubtractor, NumberAdder, less_than_3


if __name__ == "__main__":
    controller = BlackboardController()
    controller.register_predicate("less_than_3", less_than_3)
    adder, subtractor = NumberAdder(), NumberSubtractor()
    controller.add_ks(adder)
    controller.add_ks(subtractor)
    # simulate receiving a measurement
    controller.blackboard.write_entry(
        key="less_than_3",
        predicate="less_than_3",
        measurement=5)
    controller.blackboard.write_entry(
        key="is_positive",
        predicate="is_positive",
        measurement=-1)
    # controller checks eligibility and order. places key in first KS partition
    controller.route("less_than_3", [adder, subtractor])
    controller.route("is_positive", [subtractor])
    controller.run()
    print(controller.status())
    print()
    bb_history = [print(entry) for entry in controller.blackboard.get_history()]
    print("escalate")
    print(controller.blackboard.get_escalate())
