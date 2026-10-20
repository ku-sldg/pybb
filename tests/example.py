from pybb import BlackboardController, NumberSubtractor, NumberAdder, NumberNothinger, less_than_3, is_positive, is_100


if __name__ == "__main__":
    controller = BlackboardController()
    controller.register_predicate("less_than_3", less_than_3)
    controller.register_predicate("is_positive", is_positive)
    controller.register_predicate("is_100", is_100)
    adder, subtractor, nothinger = NumberAdder(), NumberSubtractor(), NumberNothinger()
    controller.add_ks(adder)
    controller.add_ks(subtractor)
    controller.add_ks(nothinger)
    # simulate receiving a measurement
    controller.blackboard.write_entry(
        key="less_than_3",
        predicate="less_than_3",
        measurement=5)
    controller.blackboard.write_entry(
        key="is_positive",
        predicate="is_positive",
        measurement=-1)
    controller.blackboard.write_entry(
        key="is_100",
        predicate="is_100",
        measurement=0)
    # controller checks eligibility and order. places key in first KS partition
    controller.route("less_than_3", [adder, subtractor])
    controller.route("is_positive", [subtractor])
    controller.route("is_100", [adder, subtractor, nothinger])
    controller.run()
    print(controller.status())
    print()
    with open("history.txt", "w") as f:
        for key, entry in controller.blackboard.get_history():
            f.write(f"{(key, entry)}\n")
    print("history written to history.txt")
    print("escalate")
    print(controller.blackboard.get_escalate())
