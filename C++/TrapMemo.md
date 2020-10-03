# Trap Memo

Write down some traps in C++ that I have met before... Ah....

## unordered_map

1. unordered_map::emplace: Inserts a new element in the unordered_map if its key is unique. This new element is constructed in place using args as the arguments for the element's constructor. The insertion only takes place if no element in the container has a key equivalent to the one being emplaced. **Only insert new element use this function, modify exist element should use insert or access index straight forward.**

## Chaos

## Update Time
2020-5-13 11:54:05