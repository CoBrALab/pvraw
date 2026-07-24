"""Study/Scan container tests: what a PvDataset exposes to the layers above it."""


def test_data_init(dataset):
    """The Study container builds from each study and lists its scans."""
    for studyobj in dataset.values():
        assert studyobj.avail, 'Study should enumerate available scans'


def test_scan_lists_its_reconstructions(dataset):
    """Every listed scan resolves to a Scan whose reconstructions are numbered."""
    for studyobj in dataset.values():
        for scan_id in studyobj.avail:
            recos = studyobj.get_scan(scan_id).avail
            assert all(isinstance(reco_id, int) for reco_id in recos)


def test_scan_binds_the_requested_reconstruction(dataset):
    """A scan reads the parameters of the reco it was asked for, not its default.

    Regression: a derived reconstruction decoded with the primary reco's word
    type and matrix failed to reshape.
    """
    for studyobj in dataset.values():
        for scan_id in studyobj.avail:
            scanobj = studyobj.get_scan(scan_id)
            if len(scanobj.avail) < 2:
                continue
            for reco_id in scanobj.avail:
                dataset_ = scanobj.get_dataset(reco_id)
                assert int(dataset_.path.parent.name) == reco_id
            return
