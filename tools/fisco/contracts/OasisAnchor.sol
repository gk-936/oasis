// SPDX-License-Identifier: Apache-2.0
pragma solidity >=0.6.10 <0.9.0;

/// Oasis tamper-evidence anchor: stores only a 32-byte digest -> (timestamp, block) mapping.
/// No payment data, names or amounts ever go on-chain. Re-anchoring an existing digest is a no-op.
contract OasisAnchor {
    struct Record { uint256 timestamp; uint256 blockNumber; address sender; }
    mapping(bytes32 => Record) private records;

    event Anchored(bytes32 indexed digest, uint256 timestamp, uint256 blockNumber, address sender);

    function anchor(bytes32 digest) public {
        if (records[digest].timestamp != 0) { return; }
        records[digest] = Record(block.timestamp, block.number, msg.sender);
        emit Anchored(digest, block.timestamp, block.number, msg.sender);
    }

    function get(bytes32 digest) public view returns (uint256, uint256, address) {
        Record storage r = records[digest];
        return (r.timestamp, r.blockNumber, r.sender);
    }
}
