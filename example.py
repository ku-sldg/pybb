from pybb import BlackboardController, NumberSubtractor, NumberAdder, less_than_3, is_positive


if __name__ == "__main__":
    controller = BlackboardController()
    controller.register_predicate("less_than_3", less_than_3)
    controller.register_predicate("is_positive", is_positive)
    controller.add_ks(NumberSubtractor())
    controller.add_ks(NumberAdder())
    # simulate receiving a measurement
    controller.blackboard.write_entry(
        key="less_than_3",
        predicate="less_than_3",
        measurement=5)
    controller.blackboard.write_entry(
        key="is_positive",
        predicate="is_positive",
        measurement=-1
    )
    controller.run()
    print(controller.status())
    print()
    bb_history = [print(entry) for entry in controller.blackboard.get_history()]
    print("escalate")
    print(controller.blackboard.get_escalate())